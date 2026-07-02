#!/usr/bin/env python3
"""Fetch the local models Reel Factory gates need.

The models are NOT committed — repo CI blocks runtime-artifact binaries (hygiene /
secret-scan). Placement and SSCD fail loud without them; run this once after
checkout:

    python fetch_models.py

Idempotent — skips models already present. Sources are OpenCV Zoo, Meta's
public SSCD model, and InsightFace's public buffalo_l release asset.
"""

from __future__ import annotations

import urllib.request
import zipfile
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
    "sscd_disc_mixup.torchscript.pt": (
        "https://dl.fbaipublicfiles.com/sscd-copy-detection/"
        "sscd_disc_mixup.torchscript.pt"
    ),
}
DEST = Path(__file__).parent / "models"
INSIGHTFACE_URL = (
    "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
)
INSIGHTFACE_DIR = DEST / "insightface" / "models" / "buffalo_l"
INSIGHTFACE_REQUIRED = ("det_10g.onnx", "w600k_r50.onnx")


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
    if not force and all(
        (INSIGHTFACE_DIR / name).exists() for name in INSIGHTFACE_REQUIRED
    ):
        print("skip insightface buffalo_l (present)")
    else:
        INSIGHTFACE_DIR.mkdir(parents=True, exist_ok=True)
        archive = INSIGHTFACE_DIR.parent / "buffalo_l.zip"
        print("fetch insightface buffalo_l ...")
        urllib.request.urlretrieve(INSIGHTFACE_URL, archive)  # noqa: S310
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(INSIGHTFACE_DIR)
        for name in INSIGHTFACE_REQUIRED:
            nested = INSIGHTFACE_DIR / "buffalo_l" / name
            if nested.exists() and not (INSIGHTFACE_DIR / name).exists():
                nested.replace(INSIGHTFACE_DIR / name)
        archive.unlink(missing_ok=True)
        missing = [
            name
            for name in INSIGHTFACE_REQUIRED
            if not (INSIGHTFACE_DIR / name).exists()
        ]
        if missing:
            raise RuntimeError(
                f"insightface buffalo_l missing files: {','.join(missing)}"
            )
        print(f"  -> {INSIGHTFACE_DIR}")
    out.extend(INSIGHTFACE_DIR / name for name in INSIGHTFACE_REQUIRED)
    return out


def main() -> int:
    fetch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
