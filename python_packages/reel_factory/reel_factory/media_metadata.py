#!/usr/bin/env python3
"""Read-only/reportable media metadata normalization helpers.

The production goal is privacy and consistency: strip generated/container
metadata when an operator explicitly normalizes an output. This module never
adds fake device, session, proxy, or platform metadata.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "reel_factory.media_metadata_normalization.v1"

# Provider names that ride in on a downloaded source filename. Stripping the
# metadata but shipping `hf_20260415_..._kling3_i2v.mp4` defeats the point --
# the filename is the one piece of metadata every platform keeps verbatim.
_PROVIDER_TOKENS = re.compile(
    r"(?:^|[_\-])"
    r"(?:hf|higgsfield|kling\d*|seedance\d*|soul|nano[_\-]?banana(?:[_\-]?pro)?"
    r"|synthid|wavespeed|wan\d*|seedream\d*|flux|grok|i2v|t2v|t2i)"
    r"(?=[_\-]|$)",
    re.IGNORECASE,
)


def output_stem(src: Path, src_hash: str) -> str:
    """Provider-free stem for a rendered output filename.

    ponytail: one regex plus one fallback, no filename parser. A Higgsfield
    export stem is a provider tag, a timestamp and a UUID -- hex and digits all
    the way down -- so once the provider tag is gone there is no human-meaningful
    label left to preserve and the content hash is a better one. A stem with any
    non-hex letter in it (`bed_lamp_gray_tank`, `boat_blue`) is operator-authored
    and survives with only the provider token removed.
    """
    stem = _PROVIDER_TOKENS.sub("_", src.stem)
    # Anything that is not a word character or a hyphen becomes an underscore.
    # Source drops carry Finder duplicates like `hf_<uuid> copy.png`, and a
    # space in an output filename breaks shell and URL handling downstream --
    # which is the whole point of renaming these.
    stem = re.sub(r"[^\w-]+", "_", stem)
    stem = re.sub(r"[_\-]{2,}", "_", stem).strip("_-")
    if not re.search(r"[g-z]", stem, re.IGNORECASE):
        return f"src_{src_hash[:10]}"
    return stem


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
