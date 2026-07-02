#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/creator-os-graphify.XXXXXX")"

cleanup() {
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

rsync -a --delete \
  --exclude '.git/' \
  --exclude '.uv-cache/' \
  --exclude '.venv/' \
  --exclude 'node_modules/' \
  --exclude 'graphify-out/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '.mypy_cache/' \
  --exclude '.turbo/' \
  --exclude 'dist/' \
  --exclude 'build/' \
  --exclude 'coverage/' \
  --exclude 'output/' \
  --exclude 'uploads/' \
  --exclude 'tmp/' \
  --exclude 'models/' \
  --exclude '00_source_videos/' \
  --exclude '02_processed/' \
  --exclude 'identity_references/' \
  "$ROOT/" "$TMP_ROOT/"

graphify extract "$TMP_ROOT" --out "$ROOT" "$@"
