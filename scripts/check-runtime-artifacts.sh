#!/usr/bin/env bash
set -euo pipefail

pattern='(^|/)(node_modules|\.venv|\.pytest_cache|__pycache__|\.next|dist|build|coverage|output|uploads|campaigns|models|graphify-out|storybook-static)/|(^|/)\.mcp\.json$|(^|/)\.env($|\.)|(^|/)Screenshot[[:space:]].*\.(png|jpg|jpeg)$|\.(mp4|mov|m4v|webm|sqlite|sqlite-shm|sqlite-wal|db)$'

if git ls-files | grep -E "$pattern"; then
  echo "Runtime artifacts must not be tracked."
  exit 1
fi
