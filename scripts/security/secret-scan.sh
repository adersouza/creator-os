#!/usr/bin/env bash
set -euo pipefail

if command -v gitleaks >/dev/null 2>&1; then
  exec gitleaks detect --source . --no-git --redact --no-banner
fi

if command -v trufflehog >/dev/null 2>&1; then
  exec trufflehog git file://. --only-verified
fi

cat >&2 <<'EOF'
No local secret scanner found.

Install one of:
  brew install gitleaks
  brew install trufflehog

CI still runs secret scanning through GitHub Actions.
EOF
exit 127
