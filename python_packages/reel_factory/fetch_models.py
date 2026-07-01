#!/usr/bin/env python3
"""Fetch the OpenCV Zoo models caption placement needs.

The models are NOT committed — repo CI blocks runtime-artifact binaries (hygiene /
secret-scan). Placement fails loud without them (see placement._warn_if_blind);
run this once after checkout:

    python fetch_models.py

Idempotent — skips models already present. Source is OpenCV Zoo (same trusted
origin used across the project).
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

_BASE = "https://github.com/opencv/opencv_zoo/raw/main/models"
MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        f"{_BASE}/face_detection_yunet/face_detection_yunet_2023mar.onnx"
    ),
    "human_segmentation_pphumanseg_2023mar.onnx": (
        f"{_BASE}/human_segmentation_pphumanseg/"
        "human_segmentation_pphumanseg_2023mar.onnx"
    ),
}
DEST = Path(__file__).parent / "models"


def fetch(*, force: bool = False) -> list[Path]:
    """Download any missing models into models/. Returns the paths present."""
    DEST.mkdir(exist_ok=True)
    out: list[Path] = []
    for name, url in MODELS.items():
        p = DEST / name
        if p.exists() and p.stat().st_size > 0 and not force:
            print(f"skip {name} (present)")
        else:
            print(f"fetch {name} ...")
            urllib.request.urlretrieve(url, p)  # noqa: S310 — pinned OpenCV Zoo URL
            print(f"  -> {p} ({p.stat().st_size} bytes)")
        out.append(p)
    return out


def main() -> int:
    fetch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
