#!/usr/bin/env bash
set -euo pipefail

failures=0
scanner_ran=0

tracked_sensitive='(^|/)(\.env($|\.)|\.mcp\.json$|.*\.sqlite($|-shm$|-wal$)|.*\.db$)'
if git ls-files | grep -E "$tracked_sensitive" >/tmp/creator-os-sensitive-files.$$; then
  echo "Tracked sensitive/runtime files are not allowed:" >&2
  sed 's/^/  /' /tmp/creator-os-sensitive-files.$$ >&2
  failures=1
fi
rm -f /tmp/creator-os-sensitive-files.$$

scan_pattern() {
  local name="$1"
  local pattern="$2"
  local tmp="/tmp/creator-os-secret-${name//[^A-Za-z0-9_]/_}.$$"
  if git grep -I -n -E -l "$pattern" -- \
      ':!docs/**' \
      ':!**/*.md' \
      ':!**/*.example' \
      ':!**/fixtures/**' \
      ':!**/tests/**' \
      ':!**/__tests__/**' \
      ':!**/*.test.*' \
      ':!**/*.spec.*' >"$tmp"; then
    echo "Potential secret pattern found: $name" >&2
    sed 's/^/  /' "$tmp" >&2
    failures=1
  fi
  rm -f "$tmp"
}

scan_pattern "juno_api_key" 'juno_ak_[A-Za-z0-9_-]{16,}'
scan_pattern "stripe_live_key" 'sk_live_[A-Za-z0-9]{16,}'
scan_pattern "supabase_service_role_jwt" 'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}'
scan_pattern "supabase_service_role_literal" 'SUPABASE_SERVICE_ROLE_KEY[[:space:]]*[:=][[:space:]]*["'\''][A-Za-z0-9._=-]{24,}["'\'']'
scan_pattern "cron_secret_literal" 'CRON_SECRET[[:space:]]*[:=][[:space:]]*["'\''][A-Za-z0-9._=-]{24,}["'\'']'
scan_pattern "encryption_key_literal" 'ENCRYPTION_KEY[[:space:]]*[:=][[:space:]]*["'\''][A-Za-z0-9._=-]{24,}["'\'']'
scan_pattern "upstash_token_literal" '(UPSTASH|QSTASH)[A-Z0-9_]*(TOKEN|SECRET|KEY)[[:space:]]*[:=][[:space:]]*["'\''][A-Za-z0-9._=-]{24,}["'\'']'
scan_pattern "meta_app_secret_literal" '(META|FACEBOOK|INSTAGRAM|THREADS)[A-Z0-9_]*(APP_SECRET|CLIENT_SECRET|ACCESS_TOKEN)[[:space:]]*[:=][[:space:]]*["'\''][A-Za-z0-9._=-]{24,}["'\'']'
scan_pattern "vercel_token_literal" 'VERCEL[A-Z0-9_]*TOKEN[[:space:]]*[:=][[:space:]]*["'\''][A-Za-z0-9._=-]{24,}["'\'']'
scan_pattern "vercel_token_value" 'vercel_[A-Za-z0-9_-]{20,}'

if command -v gitleaks >/dev/null 2>&1; then
  scanner_ran=1
  gitleaks detect --source . --no-git --redact --no-banner || failures=1
fi

if command -v trufflehog >/dev/null 2>&1; then
  scanner_ran=1
  trufflehog filesystem . --fail || failures=1
fi

if [[ "$failures" -ne 0 ]]; then
  exit "$failures"
fi

if [[ "$scanner_ran" -ne 0 ]]; then
  exit 0
fi

cat >&2 <<'EOF'
No local secret scanner found.

Install one of:
  brew install gitleaks
  brew install trufflehog

CI still runs secret scanning through GitHub Actions.
EOF
exit 0
