#!/usr/bin/env bash
set -euo pipefail

output_root="${1:-artifacts/sbom}"
mkdir -p "$output_root"

pnpm dlx @cyclonedx/cdxgen@12.8.2 \
  -t js \
  --no-install-deps \
  --no-babel \
  --output "$output_root/javascript.cdx.json" \
  .

uv export \
  --format requirements.txt \
  --all-packages \
  --all-groups \
  --frozen \
  --output-file "$output_root/python-requirements.txt"

uvx --from cyclonedx-bom==7.1.0 cyclonedx-py requirements \
  "$output_root/python-requirements.txt" \
  --pyproject pyproject.toml \
  --mc-type application \
  --spec-version 1.6 \
  --output-reproducible \
  --output-format JSON \
  --output-file "$output_root/python.cdx.json"

python3 scripts/runtime_manifest.py \
  --root "$PWD" \
  --out "$output_root/toolchain-inventory.json"

python3 - "$output_root" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
for name in ("javascript.cdx.json", "python.cdx.json"):
    payload = json.loads((root / name).read_text(encoding="utf-8"))
    if payload.get("bomFormat") != "CycloneDX" or not payload.get("components"):
        raise SystemExit(f"{name} is not a populated CycloneDX SBOM")
PY
