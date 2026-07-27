# Live weekly Audio Radar refresh

The weekly job discovers current Instagram and TikTok songs, refreshes the
private Audio Radar cache, updates lifecycle state, and safely prunes eligible
cached bytes. It never generates, exports, schedules, or publishes a Reel.

The operator-facing command is:

```sh
creator-os audio refresh --region US --max-new 20 --max-active 75 --apply
```

Use `--dry-run` for real provider discovery with zero downloads, activations,
cache deletions, or database writes.

## Private configuration

Keep the provider credentials and scheduling choices in the existing
machine-local Creator OS environment, never in the repository:

```sh
SOCIALCRAWL_API_KEY=...
TIKLIVE_API_KEY=...
CREATOR_OS_AUDIO_REFRESH_REGION=US
CREATOR_OS_AUDIO_REFRESH_MAX_NEW=20
CREATOR_OS_AUDIO_REFRESH_MAX_ACTIVE=75
CREATOR_OS_AUDIO_REFRESH_WEEKDAY=1
CREATOR_OS_AUDIO_REFRESH_HOUR=4
CREATOR_OS_AUDIO_REFRESH_MINUTE=0
CREATOR_OS_AUDIO_TIKTOK_SAMPLE_COUNT=2
CREATOR_OS_AUDIO_ACCOUNT_TRACK_COOLDOWN_DAYS=7
CREATOR_OS_AUDIO_CREATOR_SEGMENT_COOLDOWN_DAYS=14
```

`TOKCHART_API_TOKEN` remains optional and is not used by the weekly command.
The scheduled entrypoint reads
`CREATOR_OS_AUDIO_REFRESH_ENV` (default:
`~/.creator-os/generation.env`) and writes the concise latest summary to
`~/.creator-os/reports/audio-refresh/latest-summary.json`.

## Existing machine-local launchd mechanism

Install the plist outside the repository only after choosing the private
weekday and time. `Weekday` follows launchd's `0`/`7` Sunday, `1` Monday
through `6` Saturday convention.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.creator-os.audio-refresh</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/aderdesouza/.creator-os/run-job.sh</string>
    <string>audio-refresh</string>
    <string>/absolute/path/to/creator-os/scripts/run_audio_refresh.sh</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>PRIVATE_WEEKDAY</integer>
    <key>Hour</key>
    <integer>PRIVATE_HOUR</integer>
    <key>Minute</key>
    <integer>PRIVATE_MINUTE</integer>
  </dict>
  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
```

The refresh itself takes a non-blocking single-instance lock and makes one
optional Instagram request plus two bounded TikTok trending-video samples by
default. TikTok videos are aggregated by their actual music IDs before
selection, with a discovery-sample reference retained for every appearance.
The credentialed SocialCrawl payloads are stored in a private `0600` receipt for
reconciliation. Creative Center is optional
additional chart evidence and is capped at four public-page views; its
unavailability never blocks the SocialCrawl TikTok feed. TikLiveAPI only
resolves selected TikTok music IDs. TikLive resolution and total downloads are
both capped by `--max-new`. TikLive's sound owner/uploader is retained as
`soundOwner` in source metadata; it is never promoted into canonical artist
metadata or presented as the musical performer.

A provider observation counts toward lifecycle absence only when it returned
usable candidates or an explicitly valid successful empty feed. Provider
failures and invalid empty responses are unavailable observations. If every
discovery source is unavailable, the run preserves all lifecycle states,
absence counters, active tracks, and cache objects. A genuine omission from a
valid feed may increment an absence counter, but stale/prune eligibility still
requires two consecutive valid absences plus the retention protections below.

Lifecycle and retention thresholds are centralized and can be overridden in
the same private environment:

```sh
CREATOR_OS_AUDIO_STALE_AFTER_REFRESHES=2
CREATOR_OS_AUDIO_RETENTION_DAYS=30
CREATOR_OS_AUDIO_WINNER_LOOKBACK_DAYS=60
CREATOR_OS_AUDIO_WINNER_SCORE=1.0
CREATOR_OS_AUDIO_CREATIVE_REQUEST_CAP=4
```

The recommended LaunchAgent schedule is Monday at 4:00 AM machine-local time.
