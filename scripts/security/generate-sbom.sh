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

python3 - "$output_root" <<'PY'
from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def version(command: str) -> str | None:
    executable = shutil.which(command)
    if not executable:
        return None
    completed = subprocess.run(
        [executable, "-version" if command in {"ffmpeg", "ffprobe"} else "--version"],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    line = (completed.stdout or completed.stderr).splitlines()
    return line[0][:500] if line else None


root = Path.cwd()
output = Path(sys.argv[1]).resolve()
payload = {
    "schema": "creator_os.toolchain_inventory.v1",
    "platform": platform.platform(),
    "python": platform.python_version(),
    "lockfiles": {
        name: sha256(root / name)
        for name in ("pnpm-lock.yaml", "uv.lock")
        if (root / name).is_file()
    },
    "workflowFiles": {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted((root / ".github" / "workflows").glob("*.yml"))
    },
    "githubActions": sorted(
        {
            match.group(1): match.group(2)
            for path in (root / ".github" / "workflows").glob("*.yml")
            for match in re.finditer(
                r"uses:\s*([^@\s]+)@([0-9a-f]{40})",
                path.read_text(encoding="utf-8"),
            )
        }.items()
    ),
    "nativeTools": {
        tool: version(tool) for tool in ("ffmpeg", "ffprobe", "tesseract")
    },
}
(output / "toolchain-inventory.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

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
