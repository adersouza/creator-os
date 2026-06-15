#!/usr/bin/env bash
set -euo pipefail

pattern='(^|/)(node_modules|\.venv|\.next|dist|build|coverage|output|uploads|campaigns|models|graphify-out)/|\.(mp4|mov|sqlite|sqlite-shm|sqlite-wal|db)$'

if git ls-files | grep -E "$pattern"; then
  echo "Runtime artifacts must not be tracked."
  exit 1
fi

