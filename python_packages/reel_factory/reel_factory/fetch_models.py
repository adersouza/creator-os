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
import os
import tempfile
from pathlib import Path

from creator_os_core.trust_boundaries import (
    download_public_file,
    has_symlink_component,
    safe_extract_zip,
)

_BASE = "https://github.com/opencv/opencv_zoo/raw/main/models"
MODELS = {
    "face_detection_yunet_2023mar.onnx": {
        "url": f"{_BASE}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    },
    "human_segmentation_pphumanseg_2023mar.onnx": {
        "url": (
            f"{_BASE}/human_segmentation_pphumanseg/"
            "human_segmentation_pphumanseg_2023mar.onnx"
        ),
        "sha256": "552d8a984054e59b5d773d24b9b12022b22046ceb2bbc4c9aaeaceb36a9ddf24",
    },
    "sscd_disc_mixup.torchscript.pt": {
        "url": (
            "https://dl.fbaipublicfiles.com/sscd-copy-detection/"
            "sscd_disc_mixup.torchscript.pt"
        ),
        "sha256": "9f26bd4c848cc19b73d2ae92eea6e04886f61a7b764ceb7a13aeee62e6a6db56",
    },
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
INSIGHTFACE_SHA256 = "80ffe37d8a5940d59a7384c201a2a38d4741f2f3c51eef46ebb28218a7b0ca2f"
INSIGHTFACE_DIR = DEST / "insightface" / "models" / "buffalo_l"
INSIGHTFACE_REQUIRED = {
    "det_10g.onnx": "5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91",
    "w600k_r50.onnx": "4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(*, force: bool = False) -> list[Path]:
    """Download any missing models into models/. Returns the paths present."""
    DEST.mkdir(exist_ok=True)
    if has_symlink_component(DEST):
        raise RuntimeError("model destination contains a symlink")
    out: list[Path] = []
    for name, specification in MODELS.items():
        p = DEST / name
        expected = specification["sha256"]
        if p.is_symlink() or (p.exists() and not p.is_file()):
            raise RuntimeError(f"unsafe model destination: {p}")
        if p.exists() and _sha256(p) == expected and not force:
            print(f"skip {name} (present, sha256 verified)")
        else:
            print(f"fetch {name} ...")
            with tempfile.TemporaryDirectory(
                prefix=".model-download-", dir=DEST
            ) as temporary:
                candidate = Path(temporary) / name
                download_public_file(
                    specification["url"],
                    candidate,
                    expected_sha256=expected,
                    max_bytes=512 * 1024 * 1024,
                )
                os.replace(candidate, p)
                p.chmod(0o600)
            print(f"  -> {p} ({p.stat().st_size} bytes, sha256 verified)")
        out.append(p)
    if not force and all(
        (INSIGHTFACE_DIR / name).is_file()
        and not (INSIGHTFACE_DIR / name).is_symlink()
        and _sha256(INSIGHTFACE_DIR / name) == expected
        for name, expected in INSIGHTFACE_REQUIRED.items()
    ):
        print("skip insightface buffalo_l (present, sha256 verified)")
    else:
        INSIGHTFACE_DIR.mkdir(parents=True, exist_ok=True)
        print("fetch insightface buffalo_l ...")
        with tempfile.TemporaryDirectory(
            prefix=".insightface-download-", dir=DEST
        ) as temporary:
            staging = Path(temporary)
            archive = staging / "buffalo_l.zip"
            extracted = staging / "extracted"
            download_public_file(
                INSIGHTFACE_URL,
                archive,
                expected_sha256=INSIGHTFACE_SHA256,
                max_bytes=512 * 1024 * 1024,
            )
            safe_extract_zip(
                archive,
                extracted,
                max_files=64,
                max_uncompressed_bytes=1024 * 1024 * 1024,
            )
            for name, expected in INSIGHTFACE_REQUIRED.items():
                matches = [
                    candidate
                    for candidate in extracted.rglob(name)
                    if candidate.is_file() and not candidate.is_symlink()
                ]
                if len(matches) != 1:
                    raise RuntimeError(
                        f"insightface buffalo_l has ambiguous member: {name}"
                    )
                if _sha256(matches[0]) != expected:
                    raise RuntimeError(
                        f"insightface buffalo_l member SHA mismatch: {name}"
                    )
                destination = INSIGHTFACE_DIR / name
                if destination.is_symlink() or (
                    destination.exists() and not destination.is_file()
                ):
                    raise RuntimeError(
                        f"unsafe insightface model destination: {destination}"
                    )
                os.replace(matches[0], destination)
                destination.chmod(0o600)
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
