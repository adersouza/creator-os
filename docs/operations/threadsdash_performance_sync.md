# ThreadsDashboard Performance Sync

Run performance sync locally, not from GitHub Actions. The learning SQLite
databases are gitignored local state, so an ephemeral GitHub runner cannot feed
the Reel Factory learning loop.

Required environment:

```sh
export CAMPAIGN_FACTORY_SYNC_CAMPAIGN="..."
export THREADSDASH_USER_ID="..."
export SUPABASE_URL="..."
export SUPABASE_SERVICE_ROLE_KEY="..."
```

Dry-run the exact commands first:

```sh
python3 scripts/sync_threadsdash_performance.py --dry-run
```

Example `launchd` job, saved outside the repo as
`~/Library/LaunchAgents/com.creator-os.threadsdash-performance-sync.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.creator-os.threadsdash-performance-sync</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>bash</string>
    <string>-lc</string>
    <string>cd /Users/aderdesouza/Developer/creator-os &amp;&amp; source ~/.creator-os/performance-sync.env &amp;&amp; python3 scripts/sync_threadsdash_performance.py</string>
  </array>
  <key>StartInterval</key>
  <integer>3600</integer>
  <key>StandardOutPath</key>
  <string>/tmp/creator-os-performance-sync.out</string>
  <key>StandardErrorPath</key>
  <string>/tmp/creator-os-performance-sync.err</string>
</dict>
</plist>
```

Keep `~/.creator-os/performance-sync.env` local-only and mode `0600`.
