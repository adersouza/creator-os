#!/usr/bin/env python3
"""Read-only/reportable media metadata normalization helpers.

The production goal is privacy and consistency: strip generated/container
metadata when an operator explicitly normalizes an output. This module never
adds fake device, session, proxy, or platform metadata.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "reel_factory.media_metadata_normalization.v1"


def normalize_media_metadata(
    input_path: str | Path,
    *,
    output_path: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    source = Path(input_path).expanduser().resolve()
    target = Path(output_path).expanduser().resolve() if output_path else source
    exiftool = shutil.which("exiftool")
    base = {
        "schema": SCHEMA,
        "inputPath": str(source),
        "outputPath": str(target),
        "metadataNormalized": False,
        "metadataTool": "exiftool" if exiftool else "",
        "metadataWarnings": [],
        "wouldWrite": not dry_run,
        "spoofedDeviceMetadata": False,
        "spoofedPlatformMetadata": False,
    }
    if not source.exists():
        return {**base, "metadataWarnings": ["input_missing"]}
    if not exiftool:
        return {**base, "metadataWarnings": ["exiftool_unavailable"]}
    if dry_run:
        return {**base, "metadataWarnings": [], "metadataNormalized": False}
    if target != source:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    cmd = [exiftool, "-all=", "-overwrite_original", str(target)]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        warning = (proc.stderr or proc.stdout or "exiftool_failed").strip()[:500]
        return {**base, "metadataWarnings": [warning]}
    return {**base, "metadataNormalized": True, "metadataWarnings": []}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input_path")
    ap.add_argument("--output-path")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    result = normalize_media_metadata(
        args.input_path, output_path=args.output_path, dry_run=args.dry_run
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
