# Reference And Audio Refresh

Run the reference/audio refresh locally. It reads operator-owned TikTok archive
files from `~/Downloads/tiktok`, updates the local Reference Factory database,
and exports/imports the audio catalog for Campaign Factory. It does not publish,
schedule, or touch ThreadsDashboard.

## Manual Command

Dry-run or inspect local inputs first, then run:

```bash
uv run python -m reference_factory.cli import-tiktok-archive --source ~/Downloads/tiktok
uv run python -m reference_factory.cli refresh-tiktok-audio --source ~/Downloads/tiktok
uv run python -m reference_factory.cli analyze-audio-patterns
uv run python -m reference_factory.cli audio-health
```

After a healthy refresh, export the audio catalog from Reference Factory and
import it into Campaign Factory with the existing local import path:

```bash
uv run python -m reference_factory.cli list-audio \
  --export ~/Developer/reference_reels/audio_catalog.json
uv run python -m campaign_factory.cli import-audio-catalog \
  --path ~/Developer/reference_reels/audio_catalog.json
```

The ops digest already alerts when the audio catalog is older than 14 days.

## Launchd Template

Install only after the operator confirms the local TikTok archive path and
notification wrapper:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.creator-os.reference-refresh</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/aderdesouza/.creator-os/run-job.sh</string>
    <string>reference-refresh</string>
    <string>bash</string>
    <string>-lc</string>
    <string>uv run python -m reference_factory.cli import-tiktok-archive --source ~/Downloads/tiktok &amp;&amp; uv run python -m reference_factory.cli refresh-tiktok-audio --source ~/Downloads/tiktok &amp;&amp; uv run python -m reference_factory.cli analyze-audio-patterns &amp;&amp; uv run python -m reference_factory.cli audio-health &amp;&amp; uv run python -m reference_factory.cli list-audio --export ~/Developer/reference_reels/audio_catalog.json &amp;&amp; uv run python -m campaign_factory.cli import-audio-catalog --path ~/Developer/reference_reels/audio_catalog.json</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/aderdesouza/Developer/creator-os</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>0</integer>
    <key>Hour</key>
    <integer>10</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/aderdesouza/.creator-os/reference-refresh.out.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/aderdesouza/.creator-os/reference-refresh.err.log</string>
</dict>
</plist>
```

Do not install this from CI. The job depends on local archives and operator
machine state.
