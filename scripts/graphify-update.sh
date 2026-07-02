#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/creator-os-graphify.XXXXXX")"
CODE_ONLY=0
GRAPHIFY_ARGS=()

for arg in "$@"; do
  case "$arg" in
    --)
      ;;
    --code-only)
      CODE_ONLY=1
      ;;
    *)
      GRAPHIFY_ARGS+=("$arg")
      ;;
  esac
done

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

if [[ "$CODE_ONLY" == "1" ]]; then
  find "$TMP_ROOT" -type f \( \
    -iname '*.md' -o \
    -iname '*.mdx' -o \
    -iname '*.rst' -o \
    -iname '*.txt' -o \
    -iname '*.csv' -o \
    -iname '*.tsv' -o \
    -iname '*.yaml' -o \
    -iname '*.yml' -o \
    -iname '*.html' -o \
    -iname '*.pdf' -o \
    -iname '*.png' -o \
    -iname '*.jpg' -o \
    -iname '*.jpeg' -o \
    -iname '*.gif' -o \
    -iname '*.webp' -o \
    -iname '*.svg' -o \
    -iname '*.mp3' -o \
    -iname '*.wav' -o \
    -iname '*.mp4' -o \
    -iname '*.mov' -o \
    -iname '*.m4v' -o \
    -iname '*.webm' -o \
    -iname 'README' -o \
    -iname 'README.*' -o \
    -iname 'LICENSE' -o \
    -iname 'LICENSE.*' -o \
    -iname 'NOTICE' -o \
    -iname 'NOTICE.*' -o \
    -iname 'CHANGELOG' -o \
    -iname 'CHANGELOG.*' -o \
    -iname 'AGENTS' -o \
    -iname 'AGENTS.*' -o \
    -iname 'CLAUDE' -o \
    -iname 'CLAUDE.*' -o \
    -iname 'GEMINI' -o \
    -iname 'GEMINI.*' \
  \) -delete
fi

if (( ${#GRAPHIFY_ARGS[@]} )); then
  graphify extract "$TMP_ROOT" --out "$ROOT" "${GRAPHIFY_ARGS[@]}"
else
  graphify extract "$TMP_ROOT" --out "$ROOT"
fi
