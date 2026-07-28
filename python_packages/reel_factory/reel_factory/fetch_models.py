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

import hashlib
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
PINNED_MODELS = {
    "pose_landmarker_lite.task": {
        "url": (
            "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
            "pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
        ),
        "sha256": "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a",
    },
}
DEST = Path(__file__).resolve().parents[1] / "models"
INSIGHTFACE_URL = (
    "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
)
INSIGHTFACE_DIR = DEST / "insightface" / "models" / "buffalo_l"
INSIGHTFACE_REQUIRED = ("det_10g.onnx", "w600k_r50.onnx")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    for name, specification in PINNED_MODELS.items():
        p = DEST / name
        expected = specification["sha256"]
        present = p.exists() and p.stat().st_size > 0
        if present and _sha256(p) == expected and not force:
            print(f"skip {name} (present, sha256 verified)")
        else:
            print(f"fetch {name} ...")
            temporary = p.with_suffix(f"{p.suffix}.download")
            urllib.request.urlretrieve(specification["url"], temporary)  # noqa: S310
            observed = _sha256(temporary)
            if observed != expected:
                temporary.unlink(missing_ok=True)
                raise RuntimeError(
                    f"{name} sha256 mismatch: expected {expected}, observed {observed}"
                )
            temporary.replace(p)
            print(f"  -> {p} ({p.stat().st_size} bytes, sha256 verified)")
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
