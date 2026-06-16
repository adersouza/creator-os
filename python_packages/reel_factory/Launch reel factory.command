#!/bin/zsh
# Double-click this file in Finder to start the reel_factory GUI.
# Auto-opens your browser. Closing the browser tab shuts the server down.

# Resolve the directory this script lives in (so it works no matter where it's saved)
SCRIPT_DIR="$( cd "$( dirname "${(%):-%x}" )" && pwd )"
cd "$SCRIPT_DIR"

clear
cat <<'EOF'

   ┌──────────────────────────────────────┐
   │       reel factory · launching       │
   └──────────────────────────────────────┘

EOF

# Run the server. It will auto-open the browser and auto-shutdown when
# the tab is closed (server returns control here, then we close Terminal).
if [ ! -x ".venv/bin/python" ]; then
    ./setup.sh
fi
.venv/bin/python reel_gui.py

echo
echo "  reel factory stopped. you can close this window."
echo
# Auto-close the Terminal window after a short delay (best-effort —
# requires Terminal preferences to allow scripted closing).
osascript -e 'tell application "Terminal" to close (every window whose name contains "Launch reel factory")' &>/dev/null
exit 0
